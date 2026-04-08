import { Construct } from 'constructs';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface AuthProps {
  environment: string;
  /** Initial admin user email. If set, creates the user on first deploy. */
  initialUserEmail?: string;
  /** Initial admin user password. Must meet the pool's password policy. */
  initialUserPassword?: string;
  /** Display name for the initial admin user. */
  initialUserName?: string;
}

export class Auth extends Construct {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: AuthProps) {
    super(scope, id);

    this.userPool = new cognito.UserPool(this, 'UserPool', {
      userPoolName: `illuminate-users-${props.environment}`,
      signInAliases: { email: true },
      autoVerify: { email: true },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      standardAttributes: {
        email: { required: true, mutable: false },
      },
    });

    // Set UserPoolTier to LITE (not exposed in L2 construct)
    const cfnUserPool = this.userPool.node.defaultChild as cognito.CfnUserPool;
    cfnUserPool.addPropertyOverride('UserPoolTier', 'LITE');

    this.userPoolClient = new cognito.UserPoolClient(this, 'UserPoolClient', {
      userPool: this.userPool,
      userPoolClientName: `illuminate-api-${props.environment}`,
      generateSecret: false,
      authFlows: {
        userPassword: true,
        userSrp: true,
      },
    });

    // Create initial admin user on first deploy (idempotent — ignores if user exists)
    if (props.initialUserEmail && props.initialUserPassword) {
      const createUser = new cr.AwsCustomResource(this, 'InitialUser', {
        onCreate: {
          service: 'CognitoIdentityServiceProvider',
          action: 'adminCreateUser',
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: props.initialUserEmail,
            UserAttributes: [
              { Name: 'email', Value: props.initialUserEmail },
              { Name: 'email_verified', Value: 'true' },
              ...(props.initialUserName
                ? [{ Name: 'name', Value: props.initialUserName }]
                : []),
            ],
            MessageAction: 'SUPPRESS',
            TemporaryPassword: props.initialUserPassword,
          },
          physicalResourceId: cr.PhysicalResourceId.of(`initial-user-${props.initialUserEmail}`),
          ignoreErrorCodesMatching: 'UsernameExistsException',
        },
        policy: cr.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['cognito-idp:AdminCreateUser', 'cognito-idp:AdminSetUserPassword'],
            resources: [this.userPool.userPoolArn],
          }),
        ]),
      });

      // Set the permanent password (moves user from FORCE_CHANGE_PASSWORD to CONFIRMED)
      const setPassword = new cr.AwsCustomResource(this, 'InitialUserPassword', {
        onCreate: {
          service: 'CognitoIdentityServiceProvider',
          action: 'adminSetUserPassword',
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: props.initialUserEmail,
            Password: props.initialUserPassword,
            Permanent: true,
          },
          physicalResourceId: cr.PhysicalResourceId.of(`initial-user-password-${props.initialUserEmail}`),
        },
        policy: cr.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['cognito-idp:AdminSetUserPassword'],
            resources: [this.userPool.userPoolArn],
          }),
        ]),
      });

      setPassword.node.addDependency(createUser);
    }
  }
}
